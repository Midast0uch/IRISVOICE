#!/usr/bin/env python3
"""Oracle concurrency benchmark: classical lock vs Caducean phase (REQ-4).

Drives the REAL engine and the REAL ONNX model (the configured decision model
dir, see ``decision_backend_onnx.resolve_model_dir``) with one fixed workload
and writes JSON. Run it once on the lock code and once with
``IRIS_ORACLE_PHASE=1`` and compare the two files (``--compare``).

WORKLOAD (deterministic, ``build_workload``): mixed consumers with realistic
option sets and texts - ``tool_choice`` menus from the calibration fixture
``scripts/fixtures/decision_engine_cases.json``, the loop-monitor bool
consumers, ``review_verdict`` and ``narration`` - plus ONE long input at the
512-id cap (the ``done`` monitor fed a whole planner prompt, the 28.6 s case).

PROTOCOL
  1. load the engine once, warm up (not measured);
  2. ALONE: every workload item once, sequentially -> alone latency + the
     reference probability distribution;
  3. BURST (x ``--reps``): ``--threads`` threads start together on a barrier and
     each issues its share back to back; the long item sits early in thread 0;
     an ANSWER-PATH decision is issued from its own thread mid-burst under
     ``CallClass.USER_TURN`` (the priority class);
  4. record per rep: completed, wasted (None = lock timeout / given up),
     wall seconds, decisions/second, latency under load vs alone (collision
     ratio), the answer-path wait, and every distribution (compared bitwise with
     the alone reference).

MEASUREMENT RULE: keep the machine quiet while this runs.

THIRD CONFIG (2026-10-01, CONCURRENCY_MODEL S7 open thread 3): ``--config semaphore
--permits N`` - a classical control. The engine runs with NO lock and NO phase gate
(IRIS_ORACLE_PHASE=1 with the gate neutralised INSIDE THIS PROCESS ONLY), and every
decide() passes a priority semaphore of N permits: USER_TURN / SPEAK waiters go to
the front, FIFO within a level. Nothing here is shipped: decision_engine.py and
phase_domain.py are not changed (oracle.md S19.5 has the result).

Usage:
    python benchmarks/oracle_phase_bench.py --label classical
    IRIS_ORACLE_PHASE=1 python benchmarks/oracle_phase_bench.py --label phase
    python benchmarks/oracle_phase_bench.py --compare benchmarks/oracle_phase_classical.json benchmarks/oracle_phase_phase.json
"""

from __future__ import annotations

import argparse
import heapq
import json
import logging
import os
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_FIXTURE = _REPO / "scripts" / "fixtures" / "decision_engine_cases.json"

# Same pool the calibration generator draws menus from.
_TOOLS = [
    "read_file", "list_directory", "get_system_info", "recall_memory",
    "vision_analyze_screen", "vision_detect_element", "vision_validate_action",
    "create_skill", "ask_user_question", "speak", "get_rendered_documents",
]
_YESNO = ("yes", "no")
_BOOL_INSTRUCTIONS = {
    "sufficient": "Is the evidence gathered so far sufficient to answer the objective?",
    "done": "Is the objective complete?",
    "on_track": "Is the current approach still on track to complete the objective?",
}
_REVIEW_LABELS = ("pass", "refine", "veto")
_REVIEW_INSTRUCTION = "Should this completed step pass, be refined, or be vetoed?"
_NARRATION_LABELS = ("speak_all", "speak_first_only", "stay_silent")
# Jobs the original workload did not cover (oracle.md S19): interpret, guard,
# shape, classify_event - so the bench measures the real job mix.
_EXTRA = (
    ("mode", ("quick", "spec", "implement", "review"),
     "Is this a quick answer or a build task? user said: {g}"),
    ("click_safety", ("safe", "unsafe", "unsure"),
     "ACTION: click 'Delete account' on {g}"),
    ("presentation", ("plain_text", "markdown", "artifact"),
     "ANSWER HEAD: here is the comparison you asked for about {g}"),
    ("event_family", ("problem", "safety", "memory", "delivery"),
     "EVENT: step failed with a timeout while {g}"),
)
_NARRATION_INSTRUCTION = (
    "How much of this plan's narration should be spoken aloud: every beat, "
    "only the first, or nothing?"
)

_STEP_RESULTS = [
    "Read README.md: 212 lines, install steps, three open TODOs in the usage section.",
    "Listed the src folder: 41 files, 6 test modules, no build output present.",
    "Search returned 8 pages; two mention the release date, none give the changelog.",
    "Tool call failed with a timeout; retried once and the second call returned 3 rows.",
    "The screen shows the settings dialog; the Save button is greyed out.",
    "Summarised the meeting transcript into 5 bullet points and 2 action items.",
]


def _register_consumers() -> None:
    from backend.agent.decision_backend_onnx import ConsumerSpec, register_consumer_spec

    for cid, ins in _BOOL_INSTRUCTIONS.items():
        register_consumer_spec(ConsumerSpec(
            consumer_id=cid, task_name=cid, instruction=ins, labels=_YESNO))
    register_consumer_spec(ConsumerSpec(
        consumer_id="review_verdict", task_name="review_verdict",
        instruction=_REVIEW_INSTRUCTION, labels=_REVIEW_LABELS))
    register_consumer_spec(ConsumerSpec(
        consumer_id="narration", task_name="narration",
        instruction=_NARRATION_INSTRUCTION, labels=_NARRATION_LABELS))


def build_workload() -> List[Dict[str, Any]]:
    """Deterministic list of ``{consumer, options, goal, long}`` items."""
    cases = json.loads(_FIXTURE.read_text(encoding="utf-8"))["cases"]
    items: List[Dict[str, Any]] = []
    for i, case in enumerate(cases):
        menu: List[str] = []
        if case["expect"] in _TOOLS:
            menu.append(case["expect"])
        j = i
        while len(menu) < 4:
            t = _TOOLS[j % len(_TOOLS)]
            j += 3
            if t not in menu:
                menu.append(t)
        menu += ["DELEGATE", "NONE"]
        items.append({"consumer": "tool_choice", "options": menu,
                      "goal": case["goal"], "long": False})
    for i in range(18):
        cid = ("sufficient", "done", "on_track")[i % 3]
        res = " | ".join(_STEP_RESULTS[(i + k) % len(_STEP_RESULTS)] for k in range(3))
        items.append({"consumer": cid, "options": list(_YESNO), "long": False,
                      "goal": f"OBJECTIVE: answer question {i} about the project. RESULTS: {res}"})
    for i in range(6):
        items.append({"consumer": "review_verdict", "options": list(_REVIEW_LABELS),
                      "long": False,
                      "goal": f"STEP: check item {i}\nRECENT RESULTS: {_STEP_RESULTS[i % 6]}"})
    for i in range(6):
        items.append({"consumer": "narration", "options": list(_NARRATION_LABELS),
                      "long": False, "goal": f"NARRATE: tell the user about task {i}, {_STEP_RESULTS[i % 6]}"})
    for i in range(8):
        cid, labels, tmpl = _EXTRA[i % len(_EXTRA)]
        items.append({"consumer": cid, "options": list(labels), "long": False,
                      "goal": tmpl.format(g=_STEP_RESULTS[i % 6])})
    # The long input: the whole planner prompt, every step output included.
    long_goal = "OBJECTIVE: finish the report. " + " ".join(
        f"STEP {n} RESULT: {_STEP_RESULTS[n % 6]}" for n in range(400))
    items.append({"consumer": "done", "options": list(_YESNO),
                  "goal": long_goal, "long": True})
    return items


def _probs(ds: Any) -> Optional[List[Any]]:
    if ds is None:
        return None
    return [[c.name, c.logprob, c.prob] for c in ds.distribution]


def _call(eng: Any, item: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.perf_counter()
    ds = eng.decide(item["consumer"], item["options"], {"goal": item["goal"]})
    ms = (time.perf_counter() - t0) * 1000.0
    return {"ms": ms, "dist": _probs(ds), "ok": ds is not None}


def _pct(xs: List[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))]


class _PrioritySemaphore:
    """N permits; high-priority waiters go first, FIFO within a level. BENCH ONLY."""

    def __init__(self, permits: int) -> None:
        self._free = permits
        self._cv = threading.Condition()
        self._heap: List[tuple] = []
        self._seq = 0

    def acquire(self, high: bool) -> None:
        with self._cv:
            self._seq += 1
            ticket = (0 if high else 1, self._seq)
            heapq.heappush(self._heap, ticket)
            while not (self._free > 0 and self._heap[0] == ticket):
                self._cv.wait()
            heapq.heappop(self._heap)
            self._free -= 1
            self._cv.notify_all()

    def release(self) -> None:
        with self._cv:
            self._free += 1
            self._cv.notify_all()


def _install_semaphore(eng: Any, permits: int) -> None:
    """The classical control: no engine lock (phase path), no phase gate (stubbed
    in THIS process only), a priority semaphore around every decision."""
    from backend.agent import decision_engine as de
    from backend.agent.call_context import call_class, is_high_priority

    class _NoGate:
        def acquire(self, *_a: Any, **_k: Any) -> float:
            return 0.0

    de._oracle_domain = lambda: _NoGate()
    sem = _PrioritySemaphore(permits)
    inner = eng.decide

    def decide(consumer_id: str, options: Any, frame: Any, instruction: Any = None) -> Any:
        sem.acquire(is_high_priority(call_class()))
        try:
            return inner(consumer_id, options, frame, instruction)
        finally:
            sem.release()

    eng.decide = decide


_ANSWERS_PER_BURST = 5
_ANSWER_SPACING_S = 0.8


def _burst(eng: Any, items: List[Dict[str, Any]], n_threads: int,
           answer_item: int, answer_after_s: float) -> Dict[str, Any]:
    from backend.agent.call_context import CallClass, call_class_scope

    long_idx = next(i for i, it in enumerate(items) if it["long"])
    order = [i for i in range(len(items)) if i != long_idx]
    shares: List[List[int]] = [[] for _ in range(n_threads)]
    for k, idx in enumerate(order):
        shares[k % n_threads].append(idx)
    shares[0].insert(1, long_idx)  # the long input lands early in thread 0

    results: Dict[int, List[Dict[str, Any]]] = {i: [] for i in range(len(items))}
    res_lock = threading.Lock()
    answers: List[Dict[str, Any]] = []
    # workers + the answer thread + this (main) thread
    barrier = threading.Barrier(n_threads + 2)

    def worker(share: List[int]) -> None:
        barrier.wait()
        for idx in share:
            r = _call(eng, items[idx])
            with res_lock:
                results[idx].append(r)

    def answer_thread() -> None:
        # Several reply-path decisions spread through the burst, so p50/p95
        # mean something (was one per rep).
        barrier.wait()
        t0 = time.perf_counter()
        for k in range(_ANSWERS_PER_BURST):
            due = answer_after_s + k * _ANSWER_SPACING_S
            time.sleep(max(0.0, due - (time.perf_counter() - t0)))
            with call_class_scope(CallClass.USER_TURN):
                answers.append(_call(eng, items[answer_item]))

    threads = [threading.Thread(target=worker, args=(s,), name=f"bench-w{n}")
               for n, s in enumerate(shares)]
    threads.append(threading.Thread(target=answer_thread, name="bench-answer"))
    for t in threads:
        t.start()
    barrier.wait()
    t_start = time.perf_counter()
    for t in threads[:-1]:
        t.join()
    wall = time.perf_counter() - t_start
    threads[-1].join()
    return {"wall_s": wall, "results": results, "answers": answers}


def run(label: str, n_threads: int, reps: int, out: Path,
        config: str = "env", permits: int = 2) -> Dict[str, Any]:
    logging.disable(logging.WARNING - 1)  # the engine logs every decision at INFO
    if config == "semaphore":
        os.environ["IRIS_ORACLE_PHASE"] = "1"  # no engine lock; the gate is stubbed below
    from backend.agent.decision_engine import DecisionEngine, load_engine_config, oracle_job

    _register_consumers()
    items = build_workload()
    cfg = load_engine_config()
    eng = DecisionEngine(cfg)
    if not eng._load():
        raise SystemExit("MODEL DID NOT LOAD - no benchmark possible")
    if config == "semaphore":
        _install_semaphore(eng, permits)
    for it in items[:6]:  # warm-up, not measured
        eng.decide(it["consumer"], it["options"], {"goal": it["goal"]})

    # 2. ALONE reference: every item, sequentially, nothing else running.
    alone = [_call(eng, it) for it in items]
    if not all(a["ok"] for a in alone):
        raise SystemExit("an ALONE decision returned None - no reference")
    answer_item = next(i for i, it in enumerate(items)
                       if it["consumer"] == "tool_choice")
    # Mid-burst: roughly half of the serial time of the burst's own share.
    alone_total_s = sum(a["ms"] for a in alone) / 1000.0

    cnt0 = dict(eng.counters.__dict__)
    rep_out: List[Dict[str, Any]] = []
    for rep in range(reps):
        eng.counters.lock_timeouts = 0
        b = _burst(eng, items, n_threads, answer_item,
                   answer_after_s=min(1.0, alone_total_s / 4.0))
        completed = wasted = 0
        lat: List[float] = []
        ratios: List[float] = []
        diffs: List[float] = []
        bitwise_equal = 0
        compared = 0
        waits_by_consumer: Dict[str, List[float]] = {}
        waits_by_job: Dict[str, List[float]] = {}
        for idx, rs in b["results"].items():
            for r in rs:
                if not r["ok"]:
                    wasted += 1
                    continue
                completed += 1
                lat.append(r["ms"])
                ratios.append(r["ms"] / max(alone[idx]["ms"], 1e-6))
                # Fairness: the extra time under load (queueing + contention).
                cid = items[idx]["consumer"]
                w = r["ms"] - alone[idx]["ms"]
                waits_by_consumer.setdefault(cid, []).append(w)
                waits_by_job.setdefault(oracle_job(cid).name, []).append(w)
                ref, got = alone[idx]["dist"], r["dist"]
                compared += 1
                same = ref == got
                bitwise_equal += int(same)
                if not same:
                    diffs.append(max(abs(a[2] - g[2]) for a, g in zip(ref, got)))
        ans_alone = alone[answer_item]["ms"]
        ans_ms = [a["ms"] for a in b["answers"] if a.get("ok")]
        ans = {"ok": len(ans_ms) == len(b["answers"]) and bool(ans_ms),
               "ms": statistics.median(ans_ms) if ans_ms else 0.0}
        rep_out.append({
            "answer_path_ms_all": [round(x, 1) for x in ans_ms],
            "fairness_wait_ms": {
                "by_consumer": {c: {"p95": round(_pct(v, 0.95), 1), "max": round(max(v), 1)}
                                for c, v in sorted(waits_by_consumer.items())},
                "by_job": {j: {"p95": round(_pct(v, 0.95), 1), "max": round(max(v), 1)}
                           for j, v in sorted(waits_by_job.items())},
            },
            "rep": rep,
            "issued": completed + wasted,
            "completed": completed,
            "wasted": wasted,
            "lock_timeouts": eng.counters.lock_timeouts,
            "wall_s": round(b["wall_s"], 3),
            "decisions_per_s": round(completed / b["wall_s"], 3),
            "latency_ms": {"mean": round(statistics.fmean(lat), 1) if lat else None,
                           "p50": round(_pct(lat, 0.5), 1),
                           "p95": round(_pct(lat, 0.95), 1),
                           "max": round(max(lat), 1) if lat else None},
            "collision_ratio_vs_alone": {
                "median": round(statistics.median(ratios), 2) if ratios else None,
                "p95": round(_pct(ratios, 0.95), 2),
                "mean": round(statistics.fmean(ratios), 2) if ratios else None},
            "answer_path": {"ok": bool(ans.get("ok")),
                            "latency_ms": round(ans.get("ms", 0.0), 1),
                            "alone_ms": round(ans_alone, 1),
                            "wait_ms": round(ans.get("ms", 0.0) - ans_alone, 1)},
            "distributions_compared": compared,
            "distributions_bitwise_equal_to_alone": bitwise_equal,
            "max_abs_prob_diff": max(diffs) if diffs else 0.0,
        })
        print(f"[{label}] rep {rep}: completed {completed} wasted {wasted} "
              f"wall {b['wall_s']:.2f}s  {completed / b['wall_s']:.2f}/s  "
              f"answer {ans.get('ms', 0):.0f}ms (alone {ans_alone:.0f}ms)  "
              f"bitwise {bitwise_equal}/{compared}")

    backend = eng._backend
    agg = {
        "completed": sum(r["completed"] for r in rep_out),
        "wasted": sum(r["wasted"] for r in rep_out),
        "decisions_per_s_mean": round(statistics.fmean(r["decisions_per_s"] for r in rep_out), 3),
        "wall_s_mean": round(statistics.fmean(r["wall_s"] for r in rep_out), 3),
        "latency_p50_ms_mean": round(statistics.fmean(r["latency_ms"]["p50"] for r in rep_out), 1),
        "latency_p95_ms_mean": round(statistics.fmean(r["latency_ms"]["p95"] for r in rep_out), 1),
        "collision_ratio_median_mean": round(statistics.fmean(
            r["collision_ratio_vs_alone"]["median"] or 0 for r in rep_out), 2),
        "answer_path_latency_ms_mean": round(statistics.fmean(
            r["answer_path"]["latency_ms"] for r in rep_out), 1),
        "answer_path_wait_ms_mean": round(statistics.fmean(
            r["answer_path"]["wait_ms"] for r in rep_out), 1),
        "distributions_compared": sum(r["distributions_compared"] for r in rep_out),
        "distributions_bitwise_equal": sum(
            r["distributions_bitwise_equal_to_alone"] for r in rep_out),
        "max_abs_prob_diff": max(r["max_abs_prob_diff"] for r in rep_out),
    }
    _all_ans = [x for r in rep_out for x in r["answer_path_ms_all"]]
    agg["answer_path_p50_ms"] = round(_pct(_all_ans, 0.5), 1)
    agg["answer_path_p95_ms"] = round(_pct(_all_ans, 0.95), 1)
    agg["answer_path_samples"] = len(_all_ans)
    for _k in ("by_consumer", "by_job"):
        _names = sorted({n for r in rep_out for n in r["fairness_wait_ms"][_k]})
        agg[f"fairness_{_k}"] = {
            n: {"p95_mean": round(statistics.fmean(
                    r["fairness_wait_ms"][_k][n]["p95"] for r in rep_out
                    if n in r["fairness_wait_ms"][_k]), 1),
                "max": round(max(r["fairness_wait_ms"][_k][n]["max"] for r in rep_out
                                 if n in r["fairness_wait_ms"][_k]), 1)}
            for n in _names}
    doc = {
        "label": label,
        "config": config if config != "semaphore" else f"semaphore(N={permits})",
        "phase_flag": os.environ.get("IRIS_ORACLE_PHASE", "(unset)"),
        "host_cpu_count": os.cpu_count(),
        "session_options": getattr(backend, "session_options", None),
        "model_id": eng.model_id,
        "threads": n_threads,
        "reps": reps,
        "workload": {"items": len(items),
                     "by_consumer": {c: sum(1 for i in items if i["consumer"] == c)
                                     for c in sorted({i["consumer"] for i in items})},
                     "long_input_chars": max(len(i["goal"]) for i in items)},
        "alone_ms": {"mean": round(statistics.fmean(a["ms"] for a in alone), 1),
                     "p50": round(_pct([a["ms"] for a in alone], 0.5), 1),
                     "long_input": round(next(a["ms"] for a, it in zip(alone, items) if it["long"]), 1)},
        "aggregate": agg,
        "reps_detail": rep_out,
        "alone_distributions": [
            {"consumer": it["consumer"], "dist": a["dist"]} for it, a in zip(items, alone)],
        "engine_counters_start": cnt0,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"wrote {out}")
    eng.shutdown()
    return doc


def compare(a_path: str, b_path: str) -> None:
    a = json.loads(Path(a_path).read_text(encoding="utf-8"))
    b = json.loads(Path(b_path).read_text(encoding="utf-8"))
    rows = [("completed", "completed"), ("wasted", "wasted"),
            ("decisions/s", "decisions_per_s_mean"), ("wall s", "wall_s_mean"),
            ("latency p50 ms", "latency_p50_ms_mean"), ("latency p95 ms", "latency_p95_ms_mean"),
            ("collision x (median)", "collision_ratio_median_mean"),
            ("answer-path latency ms", "answer_path_latency_ms_mean"),
            ("answer-path wait ms", "answer_path_wait_ms_mean"),
            ("distributions bitwise equal", "distributions_bitwise_equal"),
            ("max abs prob diff", "max_abs_prob_diff")]
    print(f"{'metric':32s} {a['label']:>14s} {b['label']:>14s}")
    for name, key in rows:
        print(f"{name:32s} {a['aggregate'][key]!s:>14s} {b['aggregate'][key]!s:>14s}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="classical")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", default=None)
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    ap.add_argument("--config", choices=("env", "semaphore"), default="env",
                    help="env = lock or phase by IRIS_ORACLE_PHASE; semaphore = the "
                         "classical control (bench only)")
    ap.add_argument("--permits", type=int, default=2)
    args = ap.parse_args()
    if args.compare:
        compare(*args.compare)
        return 0
    out = Path(args.out) if args.out else _REPO / "benchmarks" / f"oracle_phase_{args.label}.json"
    run(args.label, args.threads, args.reps, out, args.config, args.permits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
